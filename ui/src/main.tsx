import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { buildContainer } from '@/composition/container'
import { App } from '@/presentation/app'
import { buildStore } from '@/presentation/store'
import '@/presentation/styles/tokens.css'
import '@/presentation/styles/global.css'

const container = document.getElementById('app')
if (container) {
  const store = buildStore(buildContainer().useCases)
  createRoot(container).render(
    <StrictMode>
      <Provider store={store}>
        <App />
      </Provider>
    </StrictMode>,
  )
}
