import type { Course } from "../data/mockData";

interface CourseSelectorProps {
  courses: Course[];
  selectedId: number;
  onSelect: (id: number) => void;
}

function CourseSelector({ courses, selectedId, onSelect }: CourseSelectorProps) {
  return (
    <div className="course-selector">
      {courses.map((course) => (
        <button
          key={course.id}
          className={
            course.id === selectedId ? "course-btn active" : "course-btn"
          }
          onClick={() => onSelect(course.id)}
        >
          <strong>{course.title}</strong>
          <span>{course.instructor}</span>
        </button>
      ))}
    </div>
  );
}

export default CourseSelector;