export type PillTone = 'ok' | 'warn' | 'mock' | 'bad' | 'idle'

/** The little status lamp + label in the top bar. */
export function Pill({ id, tone, children }: { id: string; tone: PillTone; children: string }) {
  return (
    <span id={id} className={tone === 'idle' ? 'pill' : `pill ${tone}`}>
      <i /> {children}
    </span>
  )
}
