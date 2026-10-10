interface FooterProps {
  centered?: boolean;
}

function Footer({ centered = false }: FooterProps) {
  if (centered) {
    return (
      <footer className="site-footer centered">
        <div className="footer-name">Knight Scribe</div>
        <p className="footer-tagline">
          Live lectures, notes, and practice in one place
        </p>
      </footer>
    );
  }

  return (
    <footer className="site-footer">
      <p>Knight Scribe, 2026</p>
    </footer>
  );
}

export default Footer;