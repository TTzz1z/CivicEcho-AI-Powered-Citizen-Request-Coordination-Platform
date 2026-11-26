export function BrandMark({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={`ce-brand-svg ${className}`.trim()}
    >
      <rect width="24" height="24" rx="6" fill="#09090B" />
      <path
        d="M7.5 16.5V11.5C7.5 9.01 9.51 7 12 7C14.49 7 16.5 9.01 16.5 11.5V16.5"
        stroke="#FFFFFF"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path
        d="M10.2 16.5V12C10.2 11.01 11.01 10.2 12 10.2C12.99 10.2 13.8 11.01 13.8 12V16.5"
        stroke="#60A5FA"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}
