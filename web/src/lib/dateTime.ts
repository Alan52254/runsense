/** Convert an athlete-local wall-clock date/time into a UTC instant without
 * using the browser's local timezone. Two offset passes handle DST changes
 * and non-whole-hour IANA zones. */
export function localDateTimeToUtcIso(
  localDate: string,
  localTime: string,
  timezone: string,
): string {
  const [year, month, day] = localDate.split("-").map(Number);
  const [hour, minute] = localTime.split(":").map(Number);
  const desiredAsUtc = Date.UTC(year, month - 1, day, hour, minute);
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  function offsetAt(instantMs: number): number {
    const values = Object.fromEntries(
      formatter
        .formatToParts(new Date(instantMs))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
    const renderedAsUtc = Date.UTC(
      values.year,
      values.month - 1,
      values.day,
      values.hour,
      values.minute,
    );
    return renderedAsUtc - instantMs;
  }

  const firstCandidate = desiredAsUtc - offsetAt(desiredAsUtc);
  return new Date(desiredAsUtc - offsetAt(firstCandidate)).toISOString();
}

/** The inverse lookup: which Athlete-local calendar date a UTC instant falls
 *  on. en-CA formats as yyyy-mm-dd, so no manual part-assembly is needed. */
export function utcInstantToLocalDate(utcMs: number, timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date(utcMs));
}
