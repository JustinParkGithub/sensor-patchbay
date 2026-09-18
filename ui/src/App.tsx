import { Hint } from './components/Hint'
import { Inspector } from './components/Inspector'
import { PatchArea } from './components/PatchArea'
import { TopBar } from './components/TopBar'
import { JackRegistryProvider } from './state/JackRegistry'
import { LiveProvider } from './state/LiveProvider'
import { PatchbayProvider } from './state/PatchbayProvider'
import { ToastProvider } from './state/ToastProvider'

/**
 * Provider order matters: the patchbay reports failures through the toast and
 * reacts to preset changes seen on the live stream, so both sit outside it.
 */
export function App() {
  return (
    <ToastProvider>
      <LiveProvider>
        <PatchbayProvider>
          <JackRegistryProvider>
            <TopBar />
            <PatchArea />
            <Hint />
            <Inspector />
          </JackRegistryProvider>
        </PatchbayProvider>
      </LiveProvider>
    </ToastProvider>
  )
}
