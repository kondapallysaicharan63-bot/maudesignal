// How other v2 screens reach "Investigate a complaint" without being edited much: the Home card and the "+" menu item
// both read this context. The classic layout never provides it, so it shows neither.
import { createContext, useContext } from 'react'

export interface InvestigateEntryApi {
  /** Opens /investigate (optionally with a product code). */
  open: (code?: string) => void
}

export const InvestigateEntry = createContext<InvestigateEntryApi | null>(null)

export const useInvestigateEntry = (): InvestigateEntryApi | null => useContext(InvestigateEntry)

/** The Home card: one sentence and the one main button. */
export function InvestigateCard({ onOpen }: { onOpen: () => void }) {
  return (
    <section className="ms2-card ms2-span2 ms2-inv-card" aria-labelledby="home-investigate-h" data-testid="home-investigate">
      <div>
        <h2 id="home-investigate-h" className="ms2-h2">
          A complaint came in?
        </h2>
        <p className="ms2-muted m-0 mt-1 text-[15px]">
          See what FDA already holds for the device type: MAUDE reports for the product code (any maker), reports not filed by a
          manufacturer, recalls and 510(k)s, with every number linked to its openFDA query.
        </p>
      </div>
      <button type="button" className="ms-btn ms-btn--primary" onClick={onOpen} data-testid="home-investigate-open">
        Investigate a complaint
      </button>
    </section>
  )
}
