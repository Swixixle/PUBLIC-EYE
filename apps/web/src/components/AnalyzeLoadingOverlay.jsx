import { useEffect, useState } from "react";

const MESSAGES = ["Reading sources…", "Extracting claims…", "Signing receipt…"];

function EyeGraphic() {
  return (
    <svg
      className="pe-eye-graphic"
      viewBox="0 0 100 50"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        className="pe-eye-lid"
        d="M 0,25 Q 50,3 100,25 Q 50,47 0,25 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle cx="50" cy="25" r="11" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle className="pe-eye-pupil" cx="50" cy="25" r="5" fill="currentColor" />
    </svg>
  );
}

export default function AnalyzeLoadingOverlay({ open }) {
  const [i, setI] = useState(0);

  useEffect(() => {
    if (!open) return undefined;
    setI(0);
    const t = window.setInterval(() => {
      setI((x) => (x + 1) % MESSAGES.length);
    }, 4000);
    return () => window.clearInterval(t);
  }, [open]);

  if (!open) return null;

  return (
    <div className="pe-overlay" role="status" aria-live="polite">
      <EyeGraphic />
      <div className="pe-overlay-wordmark">PUBLIC EYE</div>
      <div className="pe-overlay-bar" />
      <p className="pe-overlay-msg">{MESSAGES[i]}</p>
    </div>
  );
}
