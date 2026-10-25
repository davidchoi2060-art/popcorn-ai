import { ClipboardList, Headphones, Search, MessageCircle, ChevronRight } from 'lucide-react';
import {BRAND_LOGO_URL, BUILDER_BASE, CUSTOMER_BASE} from './paths.js';
export default function BrandHeader({onSaved,onHome}){
  const builderHome=e=>{if(onHome){e.preventDefault();onHome();}};
  return <header className="brand-header">
    <div className="page-container brand-header-top">
      <div className="brand-block"><a className="brand-logo-link" href={CUSTOMER_BASE} aria-label="팝콘AI 처음 화면"><img src={BRAND_LOGO_URL} alt="팝콘AI" width="420" height="153"/></a><p className="brand-patent"><span>AI 견적 기술 · 특허 출원</span><small><span className="screen-reader-only">출원번호 </span>10-2026-0151699</small></p></div>
      <form className="brand-search" action={CUSTOMER_BASE} method="get" target="_blank" role="search"><input type="hidden" name="screen" value="catalog"/><label className="screen-reader-only" htmlFor="brand-search-query">팝콘AI 상품 검색</label><input id="brand-search-query" type="search" name="q" placeholder="상품명, CPU, 그래픽카드 검색" maxLength="120" required/><button type="submit" aria-label="팝콘AI에서 검색"><Search size={22} strokeWidth={1.8}/></button></form>
      <div className="brand-header-actions"><button type="button" className="brand-tool" onClick={onSaved}><ClipboardList size={21} strokeWidth={1.65}/><span>임시 구성함</span></button><a className="brand-tool brand-help" href={CUSTOMER_BASE+'support.html'}><Headphones size={21} strokeWidth={1.65}/><span>고객지원</span></a></div>
    </div>
    <div className="brand-menu-line"><nav className="page-container brand-navigation" aria-label="주요 메뉴"><div className="brand-primary-links"><a href={CUSTOMER_BASE+'?screen=catalog'}>PC 쇼핑</a><a href={CUSTOMER_BASE+'ai-packages.html'}>AI 패키지</a><a href={CUSTOMER_BASE+'supercomputers.html'}>AI 슈퍼컴퓨터</a><a href={BUILDER_BASE} aria-current="page" onClick={builderHome}>내 PC 구성</a></div><a className="brand-ai-link" href={CUSTOMER_BASE+'?screen=chat'}><MessageCircle size={19} strokeWidth={1.7}/>AI로 PC 찾기<ChevronRight size={16}/></a></nav></div>
  </header>;
}
