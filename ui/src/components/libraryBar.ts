import { h } from '../lib/dom'
import { catalogButton } from './catalogPanel'
import { patchbay } from '../state/patchbay'
import { toast } from '../state/toast'
import type { SyncReport } from '../types'

/** Lines in a sync log that mean something went wrong, not just "updated". */
const PROBLEM = /fail|unavailable|not found|disabled|skipped|doesn't match|mismatch/i

/** The sync button's tooltip: the last report in full. */
function describeReport(report: SyncReport): string {
  const lines = [`${report.sources} source type(s), ${report.sinks} sink type(s)`, ...report.log]
  if (report.notes.length) {
    lines.push('', 'setup pip can’t do:', ...report.notes.map((n) => `  ${n.module}: ${n.note}`))
  }
  return lines.join('\n')
}

/** A file the desktop app's native picker read, base64-encoded (see app.py's Api). */
interface PickedFile {
  name: string
  data: string
}

declare global {
  interface Window {
    /** Present only inside the desktop app's native window. */
    pywebview?: { api?: { pick_files?: () => Promise<PickedFile[] | null> } }
  }
}

function decode({ name, data }: PickedFile): File {
  return new File([Uint8Array.from(atob(data), (c) => c.charCodeAt(0))], name)
}

function summarize(report: SyncReport): { text: string; bad: boolean } {
  const problems = report.log.filter((line) => PROBLEM.test(line))
  const counts = `${report.sources} sources · ${report.sinks} sinks`
  if (!problems.length) return { text: `synced — ${counts}`, bad: false }
  const first = problems[0]!.replace(/^\[modules\]\s*/, '')
  const more = problems.length > 1 ? ` (+${problems.length - 1} more, hover ⟳)` : ''
  return { text: `synced — ${counts} · ${first}${more}`, bad: true }
}

/**
 * Browse (the online module catalog: search, install, update, remove), Upload
 * (a module `.zip` or a preset `.json`, several at once, or dropped
 * anywhere on the window) and Sync, which re-reads every module and preset on
 * disk — for files added by hand to the data folder, or a module edited in place.
 */
export function libraryBar(): HTMLElement {
  const picker = h('input', { type: 'file', accept: '.zip,.json', multiple: true, hidden: true })
  const uploadBtn = h(
    'button',
    {
      id: 'uploadBtn',
      type: 'button',
      title: 'add a module (.zip of its folder) or a preset (.json) — or drop files on the window',
      onClick: () => void pick(),
    },
    'Upload…',
  )
  const syncBtn = h(
    'button',
    { id: 'syncBtn', type: 'button', title: 'Sync: re-read modules and presets', 'aria-label': 'sync' },
    '⟳',
  )

  let busy = false
  const setBusy = (on: boolean, label = '') => {
    busy = on
    uploadBtn.disabled = on
    syncBtn.disabled = on
    syncBtn.textContent = on ? label : '⟳'
  }

  const report = (result: SyncReport | null, prefix: string[] = []) => {
    if (!result) return
    syncBtn.title = `Sync: re-read modules and presets\n\nlast sync:\n${describeReport(result)}`
    const { text, bad } = summarize(result)
    toast([...prefix, text].join(' · '), bad, bad ? 6000 : undefined)
  }

  const upload = async (files: File[]) => {
    if (busy || !files.length) return
    setBusy(true, 'uploading…')
    try {
      const { lines, report: result } = await patchbay.upload(files)
      report(result, lines)
    } finally {
      setBusy(false)
    }
  }

  syncBtn.addEventListener('click', () => {
    if (busy) return
    setBusy(true, 'syncing…')
    void patchbay
      .sync()
      .then((result) => report(result))
      .finally(() => setBusy(false))
  })

  // The desktop window opens a native picker in the data folder; a browser
  // can't choose where its file dialog starts, so it gets the plain input.
  const pick = async () => {
    const native = window.pywebview?.api?.pick_files
    if (!native) return picker.click()
    const picked = await native()
    if (picked) void upload(picked.map(decode))
  }

  picker.addEventListener('change', () => {
    const files = [...(picker.files ?? [])]
    picker.value = '' // picking the same file again still fires `change`
    void upload(files)
  })

  // Drop files anywhere. Only react to drags that carry files, so dragging a
  // cable or selecting text is untouched.
  const carriesFiles = (e: DragEvent) => e.dataTransfer?.types.includes('Files') ?? false
  window.addEventListener('dragover', (e) => {
    if (!carriesFiles(e)) return
    e.preventDefault()
    document.body.classList.add('dropping')
  })
  window.addEventListener('dragleave', (e) => {
    if (e.relatedTarget === null) document.body.classList.remove('dropping')
  })
  window.addEventListener('drop', (e) => {
    if (!carriesFiles(e)) return
    e.preventDefault()
    document.body.classList.remove('dropping')
    void upload([...(e.dataTransfer?.files ?? [])])
  })

  return h('div', { className: 'group library' }, catalogButton(() => busy), uploadBtn, syncBtn, picker)
}
