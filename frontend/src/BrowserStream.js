import { useEffect, useState } from "react";

function BrowserStream({ testId }) {
  const [image, setImage] = useState(null);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!testId) return;

    const ws = new WebSocket(`ws://localhost:8000/ws/tests/${testId}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "frame") {
        setImage(`data:image/png;base64,${data.image}`);
        setStep(data.step);
      }
    };

    ws.onerror = () => console.error("WebSocket error");

    return () => ws.close();
  }, [testId]);

  return (
    <div style={{ marginTop: 20 }}>
      <h3>Live Browser (Step {step})</h3>
      {image ? (
        <img
          src={image}
          alt="browser"
          style={{ width: "100%", border: "1px solid #ccc" }}
        />
      ) : (
        <p>Waiting for frames...</p>
      )}
    </div>
  );
}

export default BrowserStream;
