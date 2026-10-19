import { AlertTriangle, CircleHelp, ScrollText } from "lucide-react"

export type Tone = "ok" | "info" | "bad" | "warn" | "policy" | "gap" | "neutral"

/** The three kinds of open item, each with its id prefix's tone and icon (D1 / P1 / G1). */
export const ITEM = {
  disagreement: { tone: "warn" as Tone, icon: AlertTriangle, word: "Disagreement" },
  policy: { tone: "policy" as Tone, icon: ScrollText, word: "Policy" },
  gap: { tone: "gap" as Tone, icon: CircleHelp, word: "Gap" },
}
