let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function clearChannelProfilerState() {
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith('cp_')) {
      localStorage.removeItem(key)
    }
  }
}
