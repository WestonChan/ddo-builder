import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import CharacterBuilder from './CharacterBuilder'

describe('CharacterBuilder', () => {
  it('renders the page heading', () => {
    render(<CharacterBuilder />)
    expect(screen.getByText('Character Builder')).toBeInTheDocument()
  })
})
