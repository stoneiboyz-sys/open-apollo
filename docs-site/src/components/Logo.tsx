export function Logomark(props: React.ComponentPropsWithoutRef<'svg'>) {
  return (
    <svg aria-hidden="true" viewBox="0 0 36 36" fill="none" {...props}>
      <circle cx="18" cy="18" r="16" stroke="#38BDF8" strokeWidth="3" />
      <path
        d="M18 8l6 20H12l6-20z"
        fill="none"
        stroke="#38BDF8"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Logo(props: React.ComponentPropsWithoutRef<'div'>) {
  return (
    <div {...props} className={`flex items-center gap-2 ${props.className ?? ''}`}>
      <Logomark className="h-8 w-8" />
      <span className="text-xl font-bold text-slate-900 dark:text-white">
        Open Apollo
      </span>
    </div>
  )
}
