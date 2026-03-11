import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import GearPlanner from './GearPlanner'

describe('GearPlanner', () => {
  it('renders the page heading', () => {
    render(<GearPlanner />)
    expect(screen.getByText('Gear Planner')).toBeInTheDocument()
  })
})
