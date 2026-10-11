import type { Course, Lecture } from "../data/mockData";

interface CourseSelectProps {
  role: "student" | "teacher";
  courses: Course[];
  lectures: Lecture[];
  loading?: boolean; // lectures not loaded yet
  onSelect: (courseId: number) => void;
  onBack: () => void;
}

function CourseSelect({
  role,
  courses,
  lectures,
  loading = false,
  onSelect,
  onBack,
}: CourseSelectProps) {
  const isTeacher = role === "teacher";

  // students only see lectures the teacher has published
  function lecturesFor(courseId: number) {
    return lectures.filter(
      (l) => l.courseId === courseId && (isTeacher || l.published)
    );
  }

  return (
    <div className="course-select">
      <button className="back-link" onClick={onBack}>
        <span aria-hidden="true">←</span> Back
      </button>

      <div className="course-hero">
        <img className="course-logo" src="/knight-logo.png" alt="" />
        <h1 className="brand-title">Knight Scribe</h1>
      </div>

      <span className="role-pill">
        {isTeacher ? "Teacher view" : "Student view"}
      </span>
      <h2 className="course-heading">
        {isTeacher ? "Your courses" : "My courses"}
      </h2>
      <p className="course-sub">
        {isTeacher
          ? "Choose a course to manage lectures and settings."
          : "Choose a course to watch lectures and study."}
      </p>

      <div className="course-grid">
        {courses.map((course) => {
          const courseLectures = lecturesFor(course.id);
          const n = courseLectures.length;
          const isLive = courseLectures.some((l) => l.isLive);
          return (
            <button
              key={course.id}
              className="course-tile"
              onClick={() => onSelect(course.id)}
            >
              <span className="course-tile-top">
                <span className="course-code">{course.description}</span>
                {isLive && (
                  <span className="course-live">
                    <span className="live-dot" />
                    Live now
                  </span>
                )}
              </span>
              <span className="course-tile-title">{course.title}</span>
              <span className="course-tile-meta">
                {course.instructor} ·{" "}
                {loading ? "loading lectures..." : `${n} ${n === 1 ? "lecture" : "lectures"}`}
              </span>
              <span className="course-tile-arrow" aria-hidden="true">
                →
              </span>
            </button>
          );
        })}

        {/* Shows judges where more courses would go */}
        <div className="course-tile placeholder" aria-disabled="true">
          <span className="course-plus">+</span>
          <span className="course-tile-title">
            {isTeacher ? "Create a course" : "Join a course"}
          </span>
          <span className="course-tile-meta">Coming soon</span>
        </div>
      </div>
    </div>
  );
}

export default CourseSelect;
