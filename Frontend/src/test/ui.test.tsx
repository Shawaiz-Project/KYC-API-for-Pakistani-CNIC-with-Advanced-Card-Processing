import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Landing } from '../pages/PublicPages'
import { StatusBadge, Stepper } from '../components/Layout'

describe('public and shared interface', () => {
  it('renders the product promise and sample-only identity art', () => {
    render(<BrowserRouter><Landing/></BrowserRouter>)
    expect(screen.getByRole('heading', {name:/identity checks/i})).toBeInTheDocument()
    expect(screen.getByText(/sample — no real identity data/i)).toBeInTheDocument()
    expect(screen.getByRole('link', {name:/start verification/i})).toHaveAttribute('href','/auth')
  })

  it('renders explicit unavailable status rather than success', () => {
    render(<StatusBadge value="unavailable"/>)
    expect(screen.getByText('unavailable')).toHaveClass('status-unavailable')
  })

  it('shows every required capture step', () => {
    render(<Stepper active={2}/>)
    for (const label of ['Document','Selfie','Liveness','Review']) expect(screen.getByText(label)).toBeInTheDocument()
  })
})
