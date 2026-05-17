import { useEffect } from 'react'

import WaitlistPage from './pages/WaitlistPage'

function App() {
  useEffect(() => {
    if (window.location.pathname !== '/waitlist') {
      window.history.replaceState(null, '', '/waitlist')
    }
    const forceWaitlist = () => {
      if (window.location.pathname !== '/waitlist') {
        window.history.replaceState(null, '', '/waitlist')
      }
    }
    window.addEventListener('popstate', forceWaitlist)
    return () => window.removeEventListener('popstate', forceWaitlist)
  }, [])

  return <WaitlistPage />
}

export default App
