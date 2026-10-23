[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$WebPort = 5173,
    # also stop the Postgres container on exit (data stays in the runsense_pgdata volume)
    [switch]$StopDbOnExit
)

# Local dev in ONE window: Postgres (docker), the API and the Vite dev server.
# The API and Vite run inside a Windows job object that dies with this
# process, so closing the window, Ctrl+C, or killing this script ends them
# too -- nothing is left holding the ports. Unlike start-runsense.ps1 it does
# not reinstall dependencies, migrate, seed, or build; run that one after a
# fresh clone.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$web = Join-Path $root "web"
$python = Join-Path $backend ".venv\Scripts\python.exe"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class KillOnCloseJob {
    [StructLayout(LayoutKind.Sequential)] struct BASIC { public long a, b; public uint LimitFlags; public UIntPtr c, d; public uint e; public UIntPtr f; public uint g, h; }
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)] struct EXT { public BASIC Basic; public IO Io; public UIntPtr p1, p2, p3, p4; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a, string n);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr j, int c, ref EXT i, uint l);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr j, IntPtr p);
    static IntPtr job = IntPtr.Zero;
    public static void Add(IntPtr process) {
        if (job == IntPtr.Zero) {
            job = CreateJobObject(IntPtr.Zero, null);
            var info = new EXT();
            info.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            SetInformationJobObject(job, 9, ref info, (uint)Marshal.SizeOf(typeof(EXT)));
        }
        AssignProcessToJobObject(job, process);
    }
}
"@

foreach ($port in @($BackendPort, $WebPort)) {
    $held = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($held) {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($held.OwningProcess)").CommandLine
        throw "Port $port is already in use by PID $($held.OwningProcess): $cmd"
    }
}
if (-not (Test-Path $python)) { throw "Missing $python -- run .\start-runsense.ps1 once to set up the backend." }
if (-not (Test-Path (Join-Path $web "node_modules"))) { throw "Missing web\node_modules -- run npm install in web\ first." }

# Windows PowerShell turns any stderr line of a native command (docker prints
# warnings there) into an error under "Stop", so judge docker by exit code.
$ErrorActionPreference = "Continue"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep 3; docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
    if ($LASTEXITCODE -ne 0) { throw "Docker did not start." }
}
Push-Location $backend
docker compose up -d --wait *> $null
$composeExit = $LASTEXITCODE
Pop-Location
if ($composeExit -ne 0) { throw "docker compose up failed (exit $composeExit)." }
$ErrorActionPreference = "Stop"
Write-Host "Postgres ready (volume runsense_pgdata)." -ForegroundColor Green

$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/runsense"
$env:COMPETITION_DEMO_ONLY = "true"
if (-not $env:DEMO_JWT_SECRET) { $env:DEMO_JWT_SECRET = "runsense-local-demo-secret-2026" }
$env:CORS_ALLOWED_ORIGINS = "http://localhost:$WebPort,http://127.0.0.1:$WebPort"
$env:VITE_API_BASE_URL = "/api"
$env:RUNSENSE_BACKEND_URL = "http://127.0.0.1:$BackendPort"

# Put THIS process in the kill-on-close job before starting anything: every
# descendant then joins the job at birth. Assigning the children afterwards
# raced the venv launcher, whose real python.exe escaped and outlived us.
[KillOnCloseJob]::Add([System.Diagnostics.Process]::GetCurrentProcess().Handle)

$children = @(
    Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $BackendPort `
        -WorkingDirectory $backend -NoNewWindow -PassThru
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npx vite --port $WebPort --strictPort" `
        -WorkingDirectory $web -NoNewWindow -PassThru
)

Write-Host "`nRunSense dev: http://localhost:$WebPort   API: http://127.0.0.1:$BackendPort/docs" -ForegroundColor Green
Write-Host "Close this window or press Ctrl+C to stop everything." -ForegroundColor DarkGray

try {
    while ($true) {
        foreach ($child in $children) {
            if ($child.HasExited) { throw "A server exited (PID $($child.Id), code $($child.ExitCode))." }
        }
        Start-Sleep 2
    }
} finally {
    foreach ($child in $children) { if (-not $child.HasExited) { Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue } }
    if ($StopDbOnExit) { $ErrorActionPreference = "Continue"; Push-Location $backend; docker compose stop *> $null; Pop-Location }
}
