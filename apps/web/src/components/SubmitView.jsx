export default function SubmitView({
  url,
  onUrlChange,
  onBlow,
  disabled,
  error,
}) {
  const raw = url ?? "";
  return (
    <div className="submit-view view-enter">
      <div className="submit-inner">
        <h1 className="submit-wordmark">WHISTLE</h1>
        <p className="submit-tagline">Audio. Text. Public record. Verified.</p>
        <hr className="submit-rule" />
        <input
          type="url"
          className="submit-input"
          placeholder="Paste a podcast, video, news article, or any URL..."
          value={url}
          onChange={(e) => onUrlChange(e.target.value)}
          autoComplete="off"
          disabled={disabled}
        />
        {raw.trim().startsWith("http") ? (
          <span className="input-mode-hint">
            Article URL detected — will extract and verify claims
          </span>
        ) : (
          <span className="input-mode-hint">Enter a claim, name, or narrative to investigate</span>
        )}
        {error ? <p className="submit-error">{error}</p> : null}
        <button
          type="button"
          className="submit-blow"
          onClick={onBlow}
          disabled={disabled || !url.trim()}
        >
          BLOW
        </button>
      </div>
    </div>
  );
}
