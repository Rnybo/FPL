import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import FdrStrip from '../FdrStrip'

// Row divs are the direct children of FdrStrip's own root div -- container is
// RTL's wrapper, so container > div is FdrStrip's root, and > div again is
// each row.
function getRows(container: HTMLElement) {
  return container.querySelectorAll(':scope > div > div')
}

describe('FdrStrip', () => {
  it('renders a single row when there are 8 or fewer difficulties (no wrap needed)', () => {
    const { container } = render(<FdrStrip difficulties={[1, 2, 3, 4, 5]} />)
    const rows = getRows(container)
    expect(rows).toHaveLength(1)
    expect(rows[0].children).toHaveLength(5)
  })

  it('wraps into two full rows of 8 when given exactly 16 difficulties -- GW1-8 then GW9-16', () => {
    const difficulties = Array.from({ length: 16 }, (_, i) => (i % 5) + 1)
    const { container } = render(<FdrStrip difficulties={difficulties} />)
    const rows = getRows(container)
    expect(rows).toHaveLength(2)
    expect(rows[0].children).toHaveLength(8)
    expect(rows[1].children).toHaveLength(8)
  })

  it('the second row holds the REMAINDER, not a full 8, when the count is not an exact multiple of 8', () => {
    const difficulties = Array.from({ length: 10 }, (_, i) => (i % 5) + 1)
    const { container } = render(<FdrStrip difficulties={difficulties} />)
    const rows = getRows(container)
    expect(rows).toHaveLength(2)
    expect(rows[0].children).toHaveLength(8)
    expect(rows[1].children).toHaveLength(2)
  })

  it('wraps into three rows for a range beyond 16 (e.g. 20 gameweeks selected)', () => {
    const difficulties = Array.from({ length: 20 }, (_, i) => (i % 5) + 1)
    const { container } = render(<FdrStrip difficulties={difficulties} />)
    const rows = getRows(container)
    expect(rows).toHaveLength(3)
    expect(rows[0].children).toHaveLength(8)
    expect(rows[1].children).toHaveLength(8)
    expect(rows[2].children).toHaveLength(4)
  })

  it('shows a dash placeholder, not an empty wrapper, when there are no difficulties at all', () => {
    const { getByText, container } = render(<FdrStrip difficulties={[]} />)
    expect(getByText('—')).toBeInTheDocument()
    expect(getRows(container)).toHaveLength(0)
  })

  it('respects a custom perRow', () => {
    const { container } = render(<FdrStrip difficulties={[1, 2, 3, 4, 5, 6]} perRow={3} />)
    const rows = getRows(container)
    expect(rows).toHaveLength(2)
    expect(rows[0].children).toHaveLength(3)
    expect(rows[1].children).toHaveLength(3)
  })
})
