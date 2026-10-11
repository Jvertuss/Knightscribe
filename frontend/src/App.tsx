import { useEffect, useState } from "react";
import Header from "./Header";
import Footer from "./Footer";
import StartScreen from "./pages/StartScreen";
import CourseSelect from "./pages/CourseSelect";
import StudentDashboard from "./pages/StudentDashboard";
import TeacherDashboard from "./pages/TeacherDashboard";
import {
  fetchDocuments,
  fetchLectures,
  loadCourses,
  loadLectures,
  loadSettings,
  saveSettings,
} from "./backend";
import {
  courses as initialCourses,
  lectures as initialLectures,
  references as initialReferences,
  defaultSettings,
} from "./data/mockData";
import type {
  Course,
  Lecture,
  ReferenceMaterial,
  CourseSettings,
} from "./data/mockData";

type Role = "student" | "teacher";

const REFRESH_MS = 5000;

// Fresh backend lectures for one course, without losing what the teacher did
// in this browser: lectures they added, and which ones they hid.
function mergeLectures(prev: Lecture[], fresh: Lecture[], courseId: number) {
  const otherCourses = prev.filter((l) => l.courseId !== courseId);
  const added = prev.filter((l) => l.courseId === courseId && l.local);
  const updated = fresh.map((f) => {
    const old = prev.find((p) => p.id === f.id);
    return old ? { ...f, published: old.published } : f;
  });
  return [...otherCourses, ...updated, ...added];
}

function App() {
  const [role, setRole] = useState<Role | null>(null);
  const [courseId, setCourseId] = useState<number | null>(null);
  const [courses, setCourses] = useState<Course[]>(initialCourses);
  const [lectures, setLectures] = useState<Lecture[]>(initialLectures);
  const [references, setReferences] =
    useState<ReferenceMaterial[]>(initialReferences);
  const [settings, setSettings] = useState<CourseSettings>(defaultSettings);

  // Load courses, then the lectures of every course (the course page shows
  // a count for each). backend.ts falls back to mock data if this fails.
  useEffect(() => {
    let cancelled = false;
    loadCourses().then(async (list) => {
      const perCourse = await Promise.all(list.map((c) => loadLectures(c.id)));
      if (cancelled) return;
      setCourses(list);
      // keep any lecture the teacher added while this was loading
      setLectures((prev) => [...perCourse.flat(), ...prev.filter((l) => l.local)]);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // While a course is open, reload its lectures every few seconds: new live
  // lectures, new transcript lines, finished recordings. If the backend can't
  // be reached, keep what is on screen. refreshKey restarts it at once.
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    if (courseId === null) return;
    const id = courseId;
    let cancelled = false;
    let timer: number | undefined;
    async function refresh() {
      try {
        const fresh = await fetchLectures(id);
        if (!cancelled) setLectures((prev) => mergeLectures(prev, fresh, id));
      } catch (err) {
        console.warn("refreshing lectures failed, keeping the current ones:", err);
      }
      if (!cancelled) timer = window.setTimeout(refresh, REFRESH_MS);
    }
    refresh();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [courseId, refreshKey]);

  // The professor's reference documents for the open course. If the backend
  // can't be reached, the mock references stay.
  useEffect(() => {
    if (courseId === null) return;
    const id = courseId;
    let cancelled = false;
    fetchDocuments(id)
      .then((docs) => {
        if (!cancelled) setReferences((prev) => [...prev.filter((r) => r.courseId !== id), ...docs]);
      })
      .catch((err) => console.warn("loading reference documents failed, keeping the current ones:", err));
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  // Settings belong to one course: load them when a course is picked.
  useEffect(() => {
    if (courseId === null) return;
    let cancelled = false;
    loadSettings(courseId).then((s) => {
      if (!cancelled) setSettings(s);
    });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  // Update the screen right away, then save to the backend.
  // If the save fails, put the old settings back.
  function updateSettings(next: CourseSettings) {
    if (courseId === null) return;
    const previous = settings;
    setSettings(next);
    saveSettings(courseId, next)
      .then(setSettings)
      .catch((err) => {
        console.error("saveSettings failed:", err);
        setSettings(previous);
      });
  }

  const course = courses.find((c) => c.id === courseId);

  // 1. Start screen
  if (role === null) {
    return <StartScreen onChoose={setRole} />;
  }

  // 2. Course selection (no Header here, the page has its own title)
  if (!course) {
    return (
      
        <CourseSelect
          role={role}
          courses={courses}
          lectures={lectures}
          onSelect={setCourseId}
          onBack={() => setRole(null)}
        />
        
      
    );
  }

  // 3. Dashboard for the chosen course
  const courseLectures = lectures.filter((l) => l.courseId === course.id);
  const courseReferences = references.filter((r) => r.courseId === course.id);
  const visibleLectures = courseLectures.filter((l) => l.published);

  return (
    <>
      <Header
        role={role}
        onRoleChange={setRole}
        onCourses={() => setCourseId(null)}
        onHome={() => {
          setRole(null);
          setCourseId(null);
        }}
      />

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
          setSettings={updateSettings}
          onRefresh={() => setRefreshKey((k) => k + 1)}
        />
      )}

      <Footer centered />
    </>
  );
}

export default App;