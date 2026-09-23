import Link from "next/link";

export function Loading({ label = "your learning space" }: { label?: string }) {
  return <div role="status" className="loading-state"><span className="loading-line" /><p>Loading {label}…</p><div className="skeleton" /><div className="skeleton short" /></div>;
}
export function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return <div role="alert" className="empty-state"><h2>A small interruption</h2><p>{message}</p><button className="button secondary" onClick={retry}>Try again</button></div>;
}
export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="empty-state"><h3>{title}</h3>{children && <p>{children}</p>}</div>;
}
export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return <nav aria-label="Breadcrumb" className="breadcrumbs"><ol><li><Link href="/">Courses</Link></li>{items.map((item, i) => <li key={i}>{item.href ? <Link href={item.href}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}</li>)}</ol></nav>;
}
