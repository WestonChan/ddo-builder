import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders the build header brand', () => {
    render(<App />)
    expect(screen.getByText('DDO Builder')).toBeInTheDocument()
  })

  it('renders collapsible sections', () => {
    render(<App />)
    expect(screen.getByText('Level Plan')).toBeInTheDocument()
    expect(screen.getByText('Gear')).toBeInTheDocument()
    expect(screen.getByText('Enhancements')).toBeInTheDocument()
    expect(screen.getByText('Epic Destinies')).toBeInTheDocument()
  })

  it('renders the stats sidebar', () => {
    render(<App />)
    expect(screen.getByText('Stats')).toBeInTheDocument()
    expect(screen.getByText('Feats')).toBeInTheDocument()
  })
})
