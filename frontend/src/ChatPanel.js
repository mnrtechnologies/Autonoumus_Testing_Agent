import { useEffect, useState } from "react";

export default function ChatPanel({ testId, status }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [waitingField, setWaitingField] = useState(null);

  useEffect(() => {
    if (!testId || status === "completed") return;

    const poll = setInterval(async () => {
      const res = await fetch(
        `http://localhost:8000/tests/${testId}/waiting`
      );
      const data = await res.json();

      if (data.waiting && data.payload) {
        setWaitingField(prev => {
          if (prev?.element_id === data.payload.element_id) {
            return prev;
          }

          setMessages(m => [
            ...m,
            {
              from: "bot",
              text: `Please enter ${data.payload.field_label}`
            }
          ]);

          return data.payload;
        });
      }
    }, 1000);

    return () => clearInterval(poll);
  }, [testId, status]);

  const sendInput = async () => {
    if (!input || !waitingField) return;

    await fetch(
      `http://localhost:8000/tests/${testId}/input`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          element_id: waitingField.element_id,
          value: input
        })
      }
    );

    setMessages(m => [...m, { from: "user", text: input }]);
    setInput("");
    setWaitingField(null);
  };

  return (
    <div className="chat-panel">
      <h3>🤖 Assistant</h3>

      <div className="chat-messages">
        {messages.map((m, i) => (
          <div
            key={i}
            className={m.from === "bot" ? "bot" : "user"}
          >
            {m.text}
          </div>
        ))}
      </div>

      {waitingField && (
        <div className="chat-input">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={`Enter ${waitingField.field_label}`}
          />
          <button onClick={sendInput}>Send</button>
        </div>
      )}
    </div>
  );
}
