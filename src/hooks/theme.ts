export const THEMES = [
  { name: 'Gold', accent: '#b8962e', hover: '#d4ad3a' },
  { name: 'Crimson', accent: '#ef4444', hover: '#f87171' },
  { name: 'Mint', accent: '#6ee7b7', hover: '#a7f3d0' },
  { name: 'Coral', accent: '#f97066', hover: '#fca5a1' },
  { name: 'Ice', accent: '#67e8f9', hover: '#a5f3fc' },
  { name: 'Marigold', accent: '#eab308', hover: '#facc15' },
  { name: 'Plum', accent: '#a855f7', hover: '#c084fc' },
  { name: 'Sand', accent: '#d6c5a3', hover: '#e8dcc4' },
  { name: 'Sage', accent: '#7ba3b8', hover: '#9bbdd0' },
]

export function applyAccent(accent: string, hover: string) {
  document.documentElement.style.setProperty('--accent', accent)
  document.documentElement.style.setProperty('--accent-hover', hover)
  localStorage.setItem('accent', JSON.stringify({ accent, hover }))
}

export function restoreAccent() {
  try {
    const stored = localStorage.getItem('accent')
    if (!stored) return
    const { accent, hover } = JSON.parse(stored)
    if (accent && hover) {
      document.documentElement.style.setProperty('--accent', accent)
      document.documentElement.style.setProperty('--accent-hover', hover)
    }
  } catch {
    // ignore malformed data
  }
}
