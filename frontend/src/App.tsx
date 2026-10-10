import { useState } from "react";
import Header from "./Header";
import Footer from "./Footer";
import StartScreen from "./pages/StartScreen";
import CourseSelect from "./pages/CourseSelect";
import StudentDashboard from "./pages/StudentDashboard";
import TeacherDashboard from "./pages/TeacherDashboard";
import {
  courses,
  lectures as initialLectures,
  references as initialReferences,
  defaultSettings,
} from "./data/mockData";
import type {
  Lecture,
  ReferenceMaterial,
  CourseSettings,
} from "./data/mockData";

type Role = "student" | "teacher";

function App() {
  const [role, setRole] = useState<Role | null>(null);
  const [courseId, setCourseId] = useState<number | null>(null);
  const [lectures, setLectures] = useState<Lecture[]>(initialLectures);
  const [references, setReferences] =
    useState<ReferenceMaterial[]>(initialReferences);
  const [settings, setSettings] = useState<CourseSettings>(defaultSettings);

  const course = courses.find((c) => c.id === courseId);

  // 1. Start screen
  if (role === null) {
    return <StartScreen onChoose={setRole} />;
  }

  // 2. Course selection (no Header here, the page has its own title)
  if (!course) {
    return (
      <>
        <CourseSelect
          role={role}
          courses={courses}
          lectures={lectures}
          onSelect={setCourseId}
          onBack={() => setRole(null)}
        />
        <Footer />
      </>
    );
  }

  // 3. Dashboard for the chosen course
  const courseLectures = lectures.filter((l) => l.courseId === course.id);
  const courseReferences = references.filter((r) => r.courseId === course.id);
  const visibleLectures = courseLectures.filter((l) => l.published);

  return (
    <>
      <Header />

      <div className="view-switch">
        <button
          className={role === "student" ? "switch-btn active" : "switch-btn"}
          onClick={() => setRole("student")}
        >
          Student view
        </button>
        <button
          className={role === "teacher" ? "switch-btn active" : "switch-btn"}
          onClick={() => setRole("teacher")}
        >
          Teacher view
        </button>
        <button className="switch-btn" onClick={() => setCourseId(null)}>
          Courses
        </button>
        <button
          className="switch-btn"
          onClick={() => {
            setRole(null);
            setCourseId(null);
          }}
        >
          Home
        </button>
      </div>

      {role === "student" ? (
        <StudentDashboard
          course={course}
          lectures={visibleLectures}
          references={courseReferences}
          settings={settings}
        />
      ) : (
        <TeacherDashboard
          course={course}
          lectures={courseLectures}
          setLectures={setLectures}
          references={courseReferences}
          setReferences={setReferences}
          settings={settings}
          setSettings={setSettings}
        />
      )}

      <Footer centered />
    </>
  );
}

export default App;