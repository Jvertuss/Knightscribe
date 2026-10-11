type Role = "student" | "teacher";

interface HeaderProps {
  role: Role;
  onRoleChange: (role: Role) => void;
  onCourses: () => void;
  onHome: () => void;
}

// Top bar on the dashboards: brand on the left, view switch and links on the right
function Header({ role, onRoleChange, onCourses, onHome }: HeaderProps) {
  return (
    <header className="topbar">
      <button className="topbar-brand" onClick={onHome} title="Back to the start screen">
        <img src="/knight-logo.png" alt="" />
        <span>Knight Scribe</span>
      </button>

      <nav className="topbar-nav">
        <div className="role-switch" aria-label="View as">
          <button
            className={role === "student" ? "active" : ""}
            aria-pressed={role === "student"}
            onClick={() => onRoleChange("student")}
          >
            Student
          </button>
          <button
            className={role === "teacher" ? "active" : ""}
            aria-pressed={role === "teacher"}
            onClick={() => onRoleChange("teacher")}
          >
            Teacher
          </button>
        </div>
        <button className="topbar-link" onClick={onCourses}>
          ← All courses
        </button>
      </nav>
    </header>
  );
}

export default Header;
