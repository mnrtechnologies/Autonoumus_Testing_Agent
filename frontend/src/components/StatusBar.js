export default function StatusBar({ status, step }) {
  return (
    <div className="status-bar">
      <span>Status: <b>{status}</b></span>
      <span>Step: <b>{step}</b></span>
    </div>
  );
}
