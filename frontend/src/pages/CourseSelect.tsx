import type { Course, Lecture } from "../data/mockData";

interface CourseSelectProps {
  role: "student" | "teacher";
  courses: Course[];
  lectures: Lecture[];
  onSelect: (courseId: number) => void;
  onBack: () => void;
}

function CourseSelect({
  role,
  courses,
  lectures,
  onSelect,
  onBack,
}: CourseSelectProps) {
  const isTeacher = role === "teacher";

  // students only count lectures the teacher has published
  function countFor(courseId: number) {
    return lectures.filter(
      (l) => l.courseId === courseId && (isTeacher || l.published)
    ).length;
  }

  return (
    <div className="course-select">
      <button className="back-link" onClick={onBack}>
        Back
      </button>

      <div className="course-hero">
        <img className="course-logo" src="/knight-logo.png" alt="" />
        <h1 className="brand-title">Knight Scribe</h1>
      </div>

      <h2 className="course-heading">
        {isTeacher ? "Your courses" : "My courses"}
      </h2>
      <p className="course-sub">Pick a course to open it</p>

      <div className="course-grid">
        {courses.map((course) => {
          const n = countFor(course.id);
          return (
            <button
              key={course.id}
              className="course-tile"
              onClick={() => onSelect(course.id)}
            >
              <span className="course-tile-title">{course.title}</span>
              <span className="course-tile-instructor">{course.instructor}</span>
              <span className="course-tile-meta">
                {n} {n === 1 ? "lecture" : "lectures"}
              </span>
            </button>
          );
        })}

        {/* Shows judges where more courses would go */}
        <div className="course-tile placeholder">
          <span className="course-plus">+</span>
          <span className="course-tile-title">
            {isTeacher ? "Create a course" : "Join a course"}
          </span>
          <span className="course-tile-desc">Coming soon</span>
        </div>
      </div>
    </div>
  );
}

export default CourseSelect;