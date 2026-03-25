export default function SubmitView({
  url,
  onUrlChange,
  onBlow,
  disabled,
  error,
}) {
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
