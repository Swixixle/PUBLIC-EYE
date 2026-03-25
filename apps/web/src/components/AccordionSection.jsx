import { useState } from "react";

export default function AccordionSection({
  title,
  statusRight,
  statusClass = "",
  defaultOpen = false,
  children,
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="accordion">
      <button
        type="button"
        className="accordion-head"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="accordion-title">
          <span className={`accordion-chevron ${open ? "open" : ""}`}>
            {open ? "▼" : "▶"}
          </span>
          {title}
        </span>
        <span className={`accordion-status ${statusClass}`}>{statusRight}</span>
      </button>
      {open ? <div className="accordion-body">{children}</div> : null}
    </div>
  );
}
