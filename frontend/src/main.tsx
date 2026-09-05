import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './tokens.css'
import './app.css'
import App from './App'

const raiz = document.getElementById('root')
if (!raiz) throw new Error('Falta #root en index.html')
createRoot(raiz).render(<StrictMode><App /></StrictMode>)
