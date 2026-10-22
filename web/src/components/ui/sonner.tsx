import { Toaster as Sonner, type ToasterProps } from "sonner"
import { Check, Info, TriangleAlert, X, Contrast } from "lucide-react"

/** Toasts styled as paper slips: sheet, hairline rule, ink text, monochrome glyphs. */
const Toaster = ({ ...props }: ToasterProps) => (
  <Sonner
    theme="light"
    className="toaster group"
    icons={{
      success: <Check className="size-4" aria-hidden />,
      info: <Info className="size-4" aria-hidden />,
      warning: <TriangleAlert className="size-4" aria-hidden />,
      error: <X className="size-4 text-signal" aria-hidden />,
      loading: <Contrast className="size-4" aria-hidden />,
    }}
    style={
      {
        "--normal-bg": "var(--surface)",
        "--normal-text": "var(--fg)",
        "--normal-border": "var(--line-strong)",
        "--border-radius": "var(--radius)",
      } as React.CSSProperties
    }
    toastOptions={{ classNames: { toast: "cn-toast font-sans", description: "!text-fg-muted" } }}
    {...props}
  />
)

export { Toaster }
