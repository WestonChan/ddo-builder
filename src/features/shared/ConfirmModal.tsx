import { useState } from 'react'
import './ConfirmModal.css'

/**
 * Generic confirmation modal with optional typed-input confirmation.
 * Renders as a fixed overlay with backdrop click to cancel.
 */
export function ConfirmModal({
  title,
  message,
  confirmLabel,
  requireInput,
  onConfirm,
  onCancel,
}: {
  title: string
  message: string
  confirmLabel: string
  requireInput?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const [inputValue, setInputValue] = useState('')
  const canConfirm = !requireInput || inputValue.toLowerCase() === requireInput.toLowerCase()

  return (
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="confirm-modal" onClick={(e) => e.stopPropagation()}>
        <div className="confirm-modal-title">{title}</div>
        <div className="confirm-modal-message">{message}</div>
        {requireInput && (
          <div className="confirm-modal-input">
            <label>
              Type <strong>{requireInput}</strong> to confirm
            </label>
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={requireInput}
              autoFocus
            />
          </div>
        )}
        <div className="confirm-modal-actions">
          <button className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn-primary" onClick={onConfirm} disabled={!canConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
