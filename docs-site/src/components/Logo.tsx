export function Logomark(props: React.ComponentPropsWithoutRef<'span'>) {
  return (
    <span
      {...props}
      className={`text-lg font-semibold tracking-tight text-slate-900 dark:text-white ${props.className ?? ''}`}
    >
      OA
    </span>
  )
}

export function Logo(props: React.ComponentPropsWithoutRef<'span'>) {
  return (
    <span
      {...props}
      className={`text-lg font-semibold tracking-tight text-slate-900 dark:text-white ${props.className ?? ''}`}
    >
      Open Apollo
    </span>
  )
}
