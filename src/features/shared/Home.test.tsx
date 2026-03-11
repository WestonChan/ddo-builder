import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Home from './Home'

describe('Home', () => {
  it('renders the page heading', () => {
    render(<Home />)
    expect(screen.getByText('DDO Build Planner')).toBeInTheDocument()
  })
})
