import { hint } from './components/hint'
import { inspector } from './components/inspector'
import { patchArea } from './components/patchArea'
import { topBar } from './components/topBar'
import { live } from './state/live'
import { patchbay } from './state/patchbay'
import './style.css'

// Every view subscribes to the stores as it is built, so build first, then
// start the stream and the boot fetch that feed them.
document.body.append(topBar(), patchArea(), hint(), inspector())
patchbay.start()
live.connect()
