import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { devLogin, sendMagicLink, setDevToken, useSignedIn } from '../auth'
import { Button, ErrorNote, ThemeToggle, Wordmark } from '../ui'

const FACTS = [
  ['982,666', 'companies in the register'],
  ['1.25M', 'annual reports read'],
  ['Weekly', 'from Bolagsverket'],
]

export function Login() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const signedIn = useSignedIn()
  const navigate = useNavigate()
  if (signedIn) return <Navigate to="/" />  // back from the magic link

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (devLogin) {
        setDevToken((await api.devLogin(email)).access_token)
        navigate('/')
      } else {
        await sendMagicLink(email)
        setSent(true)
      }
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.15fr_1fr]">
      <section className="flex flex-col justify-between border-b border-rule px-6 py-8 sm:px-10 lg:border-b-0 lg:border-r lg:px-14 lg:py-12">
        <div className="flex items-center justify-between">
          <Wordmark size="lg" />
          <ThemeToggle />
        </div>
        <div className="my-14 max-w-xl lg:my-0">
          <p className="eyebrow">Company watch · Sweden</p>
          <h1 className="mt-4 font-serif text-[2.6rem] leading-[1.05] tracking-tight sm:text-6xl xl:text-7xl">
            Know which customers won’t pay, <em className="text-signal">before</em> they don’t.
          </h1>
          <p className="mt-6 max-w-md text-[15px] leading-relaxed text-ink-2">
            Add the companies you sell to or buy from. Bolagsvakt reads their annual reports and the
            company register every week, and tells you when one starts going wrong, and why.
          </p>
        </div>
        <dl className="grid grid-cols-3 border-t border-rule-strong pt-4">
          {FACTS.map(([n, label]) => (
            <div key={label}>
              <dt className="sr-only">{label}</dt>
              <dd className="font-serif text-2xl tabular sm:text-3xl">{n}</dd>
              <dd className="mt-1 text-xs text-ink-3">{label}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="flex items-center justify-center px-6 py-14 sm:px-10">
        {sent ? (
          <div className="w-full max-w-sm">
            <p className="eyebrow">Check your inbox</p>
            <h2 className="mt-3 font-serif text-3xl tracking-tight">A sign-in link is on its way.</h2>
            <p className="mt-4 text-sm leading-relaxed text-ink-2">
              We sent it to <span className="font-medium text-ink">{email}</span>. Open it on this device
              and you’ll land straight in your watchlist.
            </p>
            <button onClick={() => setSent(false)} className="mt-6 text-sm text-ink-3 underline underline-offset-4 hover:text-ink">
              Use a different email
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="w-full max-w-sm">
            <p className="eyebrow">Sign in</p>
            <h2 className="mt-3 font-serif text-3xl tracking-tight">No password needed.</h2>
            <p className="mt-2 text-sm text-ink-2">
              {devLogin ? 'Local development: any email signs you in.' : 'We’ll email you a one-time sign-in link.'}
            </p>
            <label className="mt-8 block">
              <span className="eyebrow">Work email</span>
              <input
                type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
                className="mt-2 w-full border-0 border-b border-rule-strong bg-transparent px-0 py-2 text-lg text-ink placeholder:text-ink-3 focus:border-signal focus:outline-none focus-visible:outline-none focus:ring-0"
                placeholder="you@company.se"
              />
            </label>
            <div className="mt-4"><ErrorNote error={error} /></div>
            <Button type="submit" disabled={busy} className="mt-6 w-full py-2.5">
              {busy ? 'Sending…' : devLogin ? 'Sign in' : 'Email me a sign-in link'}
            </Button>
            <p className="mt-8 text-xs leading-relaxed text-ink-3">
              Built on Bolagsverket’s open data. A risk signal to help you decide, not a credit rating.
            </p>
          </form>
        )}
      </section>
    </div>
  )
}

export function CreateOrg({ onCreated }: { onCreated: (o: { id: string; name: string; role: 'owner' }) => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<unknown>(null)
  return (
    <form
      className="mx-auto max-w-lg py-10"
      onSubmit={async (e) => {
        e.preventDefault()
        try {
          const o = await api.createOrg(name)
          onCreated({ ...o, role: 'owner' })
        } catch (err) {
          setError(err)
        }
      }}
    >
      <p className="eyebrow">Step 1 of 2</p>
      <h1 className="mt-3 font-serif text-4xl tracking-tight">Who is doing the watching?</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-2">
        Your company’s name. The watchlist belongs to the company, so colleagues can share it later.
      </p>
      <label className="mt-8 block">
        <span className="eyebrow">Company name</span>
        <input
          required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} autoFocus
          className="mt-2 w-full border-0 border-b border-rule-strong bg-transparent px-0 py-2 text-xl text-ink placeholder:text-ink-3 focus:border-signal focus:outline-none focus-visible:outline-none focus:ring-0"
          placeholder="Grossisten i Lund AB"
        />
      </label>
      <div className="mt-4"><ErrorNote error={error} /></div>
      <Button type="submit" className="mt-6">Continue</Button>
    </form>
  )
}
