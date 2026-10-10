import type { ReferenceMaterial } from "../data/mockData";

interface ReferencePanelProps {
  references: ReferenceMaterial[];
  courseId: number;
  lectureId: number;
}

function ReferencePanel({ references, courseId, lectureId }: ReferencePanelProps) {
  const items = references.filter(
    (r) =>
      r.courseId === courseId &&
      (r.lectureId === undefined || r.lectureId === lectureId)
  );

  return (
    <div className="reference-panel">
      <h3>Reference Material</h3>

      {items.length === 0 && <p>No reference material yet.</p>}

      {items.map((item) => (
        <div key={item.id} className="reference-item">
          <span className="reference-type">{item.type}</span>
          <div>
            <strong>{item.title}</strong>
            <div className="reference-source">{item.source}</div>
          </div>
          {item.url && (
            <a href={item.url} target="_blank" rel="noreferrer">
              Open
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

export default ReferencePanel;