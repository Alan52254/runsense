import { useEffect, useRef } from "react";

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  length?: number;
  id?: string;
  error?: boolean;
}

export function OtpInput({
  value,
  onChange,
  onComplete,
  disabled = false,
  autoFocus = true,
  length = 6,
  id = "otp-input",
  error = false,
}: OtpInputProps) {
  const inputsRef = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? "");

  useEffect(() => {
    if (autoFocus) {
      const firstEmptyIdx = digits.findIndex((d) => !d);
      const targetIdx = firstEmptyIdx === -1 ? length - 1 : firstEmptyIdx;
      const timer = setTimeout(() => {
        inputsRef.current[targetIdx]?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [autoFocus]);

  function handleChange(idx: number, e: React.ChangeEvent<HTMLInputElement>) {
    const rawVal = e.target.value;
    const cleanVal = rawVal.replace(/\D/g, "");
    if (!cleanVal) {
      const newDigits = [...digits];
      newDigits[idx] = "";
      const nextVal = newDigits.join("");
      onChange(nextVal);
      return;
    }

    if (cleanVal.length > 1) {
      handleMultiInput(idx, cleanVal);
      return;
    }

    const singleDigit = cleanVal.slice(-1);
    const newDigits = [...digits];
    newDigits[idx] = singleDigit;
    const nextVal = newDigits.join("");
    onChange(nextVal);

    if (idx < length - 1) {
      inputsRef.current[idx + 1]?.focus();
      inputsRef.current[idx + 1]?.select();
    }

    if (nextVal.length === length && onComplete) {
      onComplete(nextVal);
    }
  }

  function handleMultiInput(startIdx: number, multiDigits: string) {
    const newDigits = [...digits];
    let writeIdx = startIdx;
    for (let i = 0; i < multiDigits.length && writeIdx < length; i++) {
      newDigits[writeIdx] = multiDigits[i];
      writeIdx++;
    }
    const nextVal = newDigits.join("");
    onChange(nextVal);

    const focusIdx = Math.min(writeIdx, length - 1);
    inputsRef.current[focusIdx]?.focus();

    if (nextVal.length === length && onComplete) {
      onComplete(nextVal);
    }
  }

  function handleKeyDown(idx: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace") {
      if (!digits[idx] && idx > 0) {
        e.preventDefault();
        const newDigits = [...digits];
        newDigits[idx - 1] = "";
        onChange(newDigits.join(""));
        inputsRef.current[idx - 1]?.focus();
      }
    } else if (e.key === "ArrowLeft" && idx > 0) {
      e.preventDefault();
      inputsRef.current[idx - 1]?.focus();
      inputsRef.current[idx - 1]?.select();
    } else if (e.key === "ArrowRight" && idx < length - 1) {
      e.preventDefault();
      inputsRef.current[idx + 1]?.focus();
      inputsRef.current[idx + 1]?.select();
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "");
    if (!pasted) return;
    handleMultiInput(0, pasted.slice(0, length));
  }

  return (
    <div
      className={`otp-container ${error ? "otp-error" : ""}`}
      role="group"
      aria-label="Verification Code Input"
    >
      {digits.map((digit, idx) => (
        <input
          key={idx}
          ref={(el) => {
            inputsRef.current[idx] = el;
          }}
          id={idx === 0 ? id : undefined}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={1}
          autoComplete={idx === 0 ? "one-time-code" : "off"}
          value={digit}
          disabled={disabled}
          onChange={(e) => handleChange(idx, e)}
          onKeyDown={(e) => handleKeyDown(idx, e)}
          onPaste={handlePaste}
          onFocus={(e) => e.target.select()}
          className="otp-digit-input"
          aria-label={`Digit ${idx + 1} of ${length}`}
        />
      ))}
    </div>
  );
}
