import Link from 'next/link'

/** Shared shell for the static legal pages (Terms, Privacy, Responsible Gambling). */
export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string
  updated: string
  children: React.ReactNode
}) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-8 text-sm leading-relaxed text-muted-foreground [&_a]:text-primary [&_a]:underline [&_h2]:mt-6 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-foreground [&_li]:ml-5 [&_li]:list-disc [&_p]:mb-3 [&_strong]:text-foreground">
      <h1 className="mb-1 text-2xl font-bold text-foreground">{title}</h1>
      <p className="text-xs">Last updated: {updated}</p>
      {children}
      <p className="mt-8 text-xs">
        See also: <Link href="/terms">Terms of Service</Link> ·{' '}
        <Link href="/privacy">Privacy Policy</Link> ·{' '}
        <Link href="/responsible-gambling">Responsible Gambling</Link>
      </p>
    </article>
  )
}
