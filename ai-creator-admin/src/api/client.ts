import axios from 'axios'

function readCookie(name: string) {
  return document.cookie.split('; ').find(row => row.startsWith(`${name}=`))?.split('=')[1] || ''
}

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE || '/v1', withCredentials: true })
api.interceptors.request.use(config => {
  const csrf = readCookie('csrf_token')
  if (csrf) config.headers['X-CSRF-Token'] = decodeURIComponent(csrf)
  return config
})
api.interceptors.response.use(response => response, error => {
  const message = error.response?.data?.detail || error.message || '请求失败'
  return Promise.reject(new Error(message))
})

