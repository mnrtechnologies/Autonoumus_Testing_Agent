export default function BrowserView({ frame }) {
  return (
    <div className="browser-container">
      {frame ? (
        <img src={frame} alt="Live Browser" className="browser-frame" />
      ) : (
        <div className="placeholder">Waiting for browser stream…</div>
      )}
    </div>
  );
}
