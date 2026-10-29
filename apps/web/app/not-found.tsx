import Link from "next/link";

export default function NotFoundPage() {
  return <main className="error-state"><h1>That page is not here.</h1><p>The route may have moved or you may not have access to it.</p><Link className="button button-primary" href="/">Return home</Link></main>;
}
