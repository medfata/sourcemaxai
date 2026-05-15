import { useCallback, useEffect, useRef, useState } from 'react'

import './ConfirmDialog.css'

export type ConfirmVariant = 'default' | 'danger'

export interface ConfirmOptions {
  title?: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: ConfirmVariant
  /**
   * Optional async action run when user confirms. If provided, the dialog stays
   * open and shows a spinner while it runs. On rejection the dialog stays open
   * and shows the error inline; on resolution the dialog closes and the promise
   * returned by `confirm()` resolves to `true`.
   */
  action?: () => Promise<void> | void
}

interface ConfirmDialogProps {
  open: boolean
  title?: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: ConfirmVariant
  pending?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  pending = false,
  error = null,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (pending) return
        e.preventDefault()
        onCancel()
      } else if (e.key === 'Enter') {
        if (pending) return
        e.preventDefault()
        onConfirm()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      prev?.focus?.()
    }
  }, [open, pending, onCancel, onConfirm])

  if (!open) return null

  return (
    <div
      className="confirm-dialog-overlay"
      role="presentation"
      onMouseDown={(e) => {
        if (pending) return
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div
        className={`confirm-dialog ${variant === 'danger' ? 'is-danger' : ''}`}
        role="alertdialog"
        aria-modal="true"
        aria-busy={pending || undefined}
        aria-labelledby={title ? 'confirm-dialog-title' : undefined}
        aria-describedby="confirm-dialog-message"
      >
        <div className="confirm-dialog-eyebrow">
          <span className="confirm-dialog-eyebrow-dot" aria-hidden />
          {variant === 'danger' ? 'Confirm action · destructive' : 'Confirm action'}
        </div>
        {title && (
          <h2 id="confirm-dialog-title" className="confirm-dialog-title">
            {title}
          </h2>
        )}
        <p id="confirm-dialog-message" className="confirm-dialog-message">
          {message}
        </p>

        {error && (
          <div className="confirm-dialog-error" role="alert">
            <span className="confirm-dialog-error-dot" aria-hidden />
            <span>{error}</span>
          </div>
        )}

        <div className="confirm-dialog-actions">
          <button
            type="button"
            className="confirm-dialog-btn secondary"
            onClick={onCancel}
            disabled={pending}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`confirm-dialog-btn ${variant === 'danger' ? 'danger' : 'primary'}`}
            onClick={onConfirm}
            disabled={pending}
            aria-busy={pending || undefined}
          >
            {pending && <span className="confirm-dialog-spinner" aria-hidden />}
            {pending ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

export function useConfirm() {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resolverRef = useRef<((v: boolean) => void) | null>(null)

  const close = useCallback((value: boolean) => {
    resolverRef.current?.(value)
    resolverRef.current = null
    setOpts(null)
    setPending(false)
    setError(null)
  }, [])

  const confirm = useCallback((options: ConfirmOptions) => {
    setError(null)
    setPending(false)
    setOpts(options)
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve
    })
  }, [])

  const handleConfirm = useCallback(async () => {
    if (!opts) return
    setError(null)
    if (!opts.action) {
      close(true)
      return
    }
    setPending(true)
    try {
      await opts.action()
      close(true)
    } catch (e) {
      setPending(false)
      setError(e instanceof Error && e.message ? e.message : 'Action failed')
    }
  }, [opts, close])

  const handleCancel = useCallback(() => {
    if (pending) return
    close(false)
  }, [pending, close])

  const dialog = (
    <ConfirmDialog
      open={opts !== null}
      title={opts?.title}
      message={opts?.message ?? ''}
      confirmLabel={opts?.confirmLabel}
      cancelLabel={opts?.cancelLabel}
      variant={opts?.variant}
      pending={pending}
      error={error}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  )

  return { confirm, dialog }
}
