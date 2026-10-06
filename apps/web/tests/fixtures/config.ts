const values: Record<string, string> = {
  NEXT_PUBLIC_LEARNHOUSE_DOMAIN: 'school.example.com',
  NEXT_PUBLIC_LEARNHOUSE_HTTPS: 'true',
}

export const testConfig = {
  getConfig: (key: string, fallback = '') => values[key] || fallback,
  getServerAPIUrl: () => 'https://api.example.com/api/v1/',
  getPlatformUrl: () => '',
  getUriWithoutOrg: (path: string) => path,
  getUriWithOrg: (_orgslug: string, path: string) => path,
}
