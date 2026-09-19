import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

i18n.use(initReactI18next).init({
  fallbackLng: 'en',
  interpolation: {escapeValue: false},
  resources: {
    en: {translation: {home:'Home', newVerification:'New verification', applications:'Applications', help:'Help', settings:'Settings', reviewQueue:'Review queue', analytics:'Analytics', apiAccess:'API access', signOut:'Sign out'}},
    ur: {translation: {home:'ہوم', newVerification:'نئی تصدیق', applications:'درخواستیں', help:'مدد', settings:'ترتیبات', reviewQueue:'جائزہ قطار', analytics:'تجزیات', apiAccess:'اے پی آئی رسائی', signOut:'سائن آؤٹ'}},
  },
})

export function setLanguage(language: 'en'|'ur') {
  i18n.changeLanguage(language)
  document.documentElement.lang = language
  document.documentElement.dir = language === 'ur' ? 'rtl' : 'ltr'
}

export default i18n
