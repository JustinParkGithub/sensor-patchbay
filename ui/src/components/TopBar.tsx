import { PanicButton } from './PanicButton'
import { PresetBar } from './PresetBar'
import { StatusBar } from './StatusBar'

export function TopBar() {
  return (
    <header id="bar">
      <div className="brand">
        <span className="glyph">▚</span> joycon&#8202;·&#8202;patchbay
      </div>
      <PresetBar />
      <div className="spacer" />
      <StatusBar />
      <PanicButton />
    </header>
  )
}
