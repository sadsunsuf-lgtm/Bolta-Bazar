import React, { useState, useEffect, useMemo, useCallback } from 'react';
import VoiceRecorder from './components/VoiceRecorder';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const TRANSLATIONS = {
    title: { en: 'Bolta Bazaar', ur: 'بولتا بازار' },
    status: { en: 'Gemini 1.5 Pro: Connected', ur: 'جیمنی ١.٥ پرو: منسلک ہے' },
    statsTitle1: { en: "Recent Activity", ur: "حالیہ سرگرمی" },
    statsTitle2: { en: "Top Selling Item", ur: "سب سے زیادہ بکنے والی چیز" },
    statsTitle3: { en: "Inventory Alerts", ur: "اسٹاک الرٹس" },
    voiceEntry: { en: "Voice Command Entry", ur: "آواز کے ذریعے داخل کریں" },
    liveTranscription: { en: "Live AI Transcription", ur: "لائیو ٹرانسکرپشن" },
    inventoryTable: { en: "Real-time Stock Ledger", ur: "اسٹاک کی صورتحال" },
    colItem: { en: "Item Name", ur: "آئٹم کا نام" },
    colStock: { en: "Current Stock", ur: "موجودہ اسٹاک" },
    colLastUpdated: { en: "Last Updated", ur: "آخری اپ ڈیٹ" },
    colAction: { en: "Quick Actions", ur: "ایکشن" },
    waitingVoice: { en: "Waiting for voice input...", ur: "آواز کے ان پٹ کا انتظار ہے..." },
    units: { en: "Kg", ur: "کلو" },
    noActivity: { en: "No recent transactions", ur: "کوئی حالیہ سرگرمی نہیں" },
    allGood: { en: "All Good", ur: "سب ٹھیک ہے" },
    listening: { en: 'Listening...', ur: 'سن رہا ہوں...' },
    sendingToAI: { en: 'Sending to AI...', ur: 'AI کو بھیج رہا ہے...' },
    recording: { en: 'Recording', ur: 'ریکارڈنگ' },
    processingVoice: { en: 'Processing...', ur: 'پروسیسنگ ہو رہی ہے...' },
    tapToRecord: { en: 'Tap to record', ur: 'بولنے کے لیے دبائیں' },
    logAdded: { en: 'Added {qty} {name}', ur: '{name} میں {qty} کا اضافہ' },
    logSold: { en: 'Sold {qty} {name}', ur: '{name} کی {qty} فروخت' },
    logUpdated: { en: 'Updated {name}', ur: '{name} اپ ڈیٹ ہو گیا' }
};

const getTranslatedName = (name, lang) => {
    if (!name) return "";
    const dict = {
        'aata': { en: 'Flour', ur: 'آٹا' },
        'flour': { en: 'Flour', ur: 'آٹا' },
        'rice': { en: 'Rice', ur: 'چاول' },
        'sugar': { en: 'Sugar', ur: 'چینی' },
        'oil': { en: 'Oil', ur: 'تیل' },
        'cooking oil': { en: 'Cooking Oil', ur: 'کوکنگ آئل' },
        'cooking_oil': { en: 'Cooking Oil', ur: 'کوکنگ آئل' },
        'maida': { en: 'Maida', ur: 'میدہ' },
        'lentils': { en: 'Lentils', ur: 'دالیں' },
        'salt': { en: 'Salt', ur: 'نمک' }
    };
    const lookup = name.toLowerCase().trim();
    return dict[lookup] ? dict[lookup][lang] : name;
};

function App() {
    const [lang, setLang] = useState('en');
    const [liveTranscript, setLiveTranscript] = useState('');
    const [inventory, setInventory] = useState([]);
    const [transactionLog, setTransactionLog] = useState([]);
    const [isLoading, setIsLoading] = useState(true);

    const getText = useCallback((key, params = {}) => {
        let text = TRANSLATIONS[key] ? (TRANSLATIONS[key][lang] || TRANSLATIONS[key]['en']) : key;
        if (params.name) text = text.replace('{name}', getTranslatedName(params.name, lang));
        if (params.qty) text = text.replace('{qty}', params.qty);
        return text;
    }, [lang]);

    const formatDate = (dateString) => {
        if (!dateString) return "Recently";
        const date = new Date(dateString);
        return isNaN(date.getTime()) ? "Recently" :
            date.toLocaleDateString('en-US', { day: 'numeric', month: 'short' }) + ', ' +
            date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    };

    const fetchInventory = async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/api/inventory`);
            if (!response.ok) throw new Error('Network response was not ok');
            const data = await response.json();
            if (Array.isArray(data)) {
                const sorted = data.sort((a, b) =>
                    new Date(b.lastUpdated || 0) - new Date(a.lastUpdated || 0)
                );
                setInventory(sorted);
            }
        } catch (error) {
            console.error('Error fetching inventory:', error);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchInventory();
    }, []);

    const topSellingItem = useMemo(() => {
        if (inventory.length === 0) return null;
        const withSales = inventory.filter(i => (i.sales || 0) > 0);
        if (withSales.length === 0) return null;
        return [...withSales].sort((a, b) => (b.sales || 0) - (a.sales || 0))[0];
    }, [inventory]);

    const handleVoiceResult = async (data) => {
        const newItem = data.updated_inventory_item || data.updatedItem || data.item;
        if (newItem) {
            setLiveTranscript('');
            await fetchInventory();
            const actionKey = data.action === 'sale' ? 'logSold' : (data.action === 'add' ? 'logAdded' : 'logUpdated');
            setTransactionLog(prev => [{ key: actionKey, name: data.item, qty: data.qty }, ...prev].slice(0, 10));
        }
    };

    const handleManualAdjustment = async (item, delta) => {
        try {
            const response = await fetch(`${API_BASE_URL}/api/inventory/adjust`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: item.name, delta: delta })
            });
            if (!response.ok) throw new Error('Update failed');
            const updatedItem = await response.json();
            if (updatedItem && !updatedItem.error) {
                setInventory(prev => prev.map(i =>
                    (i.id === updatedItem.id || i.name.toLowerCase() === updatedItem.name.toLowerCase())
                        ? updatedItem : i
                ));
                const actionKey = delta > 0 ? 'logAdded' : 'logSold';
                setTransactionLog(logs => [{ key: actionKey, name: item.name, qty: Math.abs(delta) }, ...logs].slice(0, 10));
            }
        } catch (error) {
            console.error('Manual adjustment failed:', error);
        }
    };

    const lowStockItems = inventory.filter(i => (i.stock || 0) < 5);

    if (isLoading) return (
        <div className="min-h-screen flex items-center justify-center bg-[#f8fafc]">
            <div className="text-center animate-pulse">
                <p className="font-bold text-blue-600">Bolta Bazaar Connecting...</p>
            </div>
        </div>
    );

    return (
        <div className={`min-h-screen flex flex-col bg-[#f8fafc] ${lang === 'ur' ? 'font-urdu' : ''}`} dir={lang === 'ur' ? 'rtl' : 'ltr'}>
            <header className="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center sticky top-0 z-50">
                <div className="flex items-center gap-3">
                    <div className="bg-blue-600 text-white p-2.5 rounded-xl">
                        <span className="text-2xl">🛒</span>
                    </div>
                    <div>
                        <h1 className="text-2xl font-black text-gray-900">{getText('title')}</h1>
                        <p className="text-[10px] text-gray-500 font-bold uppercase tracking-widest">{getText('status')}</p>
                    </div>
                </div>
                <button onClick={() => setLang(lang === 'en' ? 'ur' : 'en')} className="px-6 py-2.5 bg-gray-900 text-white rounded-full font-bold hover:bg-gray-800 transition-all shadow-md">
                    {lang === 'en' ? 'اردو' : 'English'}
                </button>
            </header>

            <main className="flex-grow p-4 md:p-8 max-w-7xl mx-auto w-full flex flex-col gap-8">
                <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100 flex flex-col h-32">
                        <h3 className="text-xs font-bold text-gray-400 mb-2 uppercase">{getText('statsTitle1')}</h3>
                        <p className="font-bold text-gray-800 truncate">
                            {transactionLog[0] ? getText(transactionLog[0].key, transactionLog[0]) : getText('noActivity')}
                        </p>
                    </div>
                    <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100 flex flex-col h-32">
                        <h3 className="text-xs font-bold text-gray-400 mb-2 uppercase">{getText('statsTitle2')}</h3>
                        <span className="text-2xl font-black text-blue-600">{topSellingItem ? getTranslatedName(topSellingItem.name, lang) : '---'}</span>
                    </div>
                    <div className={`p-6 rounded-3xl shadow-sm border flex flex-col h-32 ${lowStockItems.length > 0 ? 'bg-red-50 border-red-100' : 'bg-white'}`}>
                        <h3 className="text-xs font-bold text-gray-400 mb-2 uppercase">{getText('statsTitle3')}</h3>
                        <span className={`text-2xl font-black ${lowStockItems.length > 0 ? 'text-red-600' : 'text-green-500'}`}>
                            {lowStockItems.length > 0 ? lowStockItems.length : getText('allGood')}
                        </span>
                    </div>
                </section>

                <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="bg-white rounded-[2rem] shadow-xl border p-8 flex flex-col items-center justify-center min-h-[250px]">
                        <h2 className="text-sm font-black text-gray-400 uppercase tracking-widest mb-6">{getText('voiceEntry')}</h2>
                        <VoiceRecorder
                            onResult={handleVoiceResult}
                            onTranscriptUpdate={(t) => setLiveTranscript(t)}
                            lang={lang}
                            getText={getText}
                        />
                    </div>
                    <div className="bg-gray-900 rounded-[2rem] shadow-2xl p-8 flex flex-col justify-center">
                        <h2 className="text-[10px] font-black text-blue-400 uppercase tracking-widest mb-4">{getText('liveTranscription')}</h2>
                        <p className="text-3xl font-medium text-white leading-relaxed">{liveTranscript || getText('waitingVoice')}</p>
                    </div>
                </section>

                <section className="bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden">
                    <div className="p-8 border-b">
                        <h2 className="text-xl font-black text-gray-900">{getText('inventoryTable')}</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="bg-gray-50 text-[10px] text-gray-400 uppercase font-black">
                                    <th className="px-8 py-4 text-start">{getText('colItem')}</th>
                                    <th className="px-8 py-4 text-center">{getText('colStock')}</th>
                                    <th className="px-8 py-4 text-center">{getText('colLastUpdated')}</th>
                                    <th className="px-8 py-4 text-center">{getText('colAction')}</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y">
                                {inventory.map((item) => (
                                    <tr key={item.id || item.name} className="hover:bg-blue-50/30 transition-colors">
                                        <td className="px-8 py-6">
                                            <span className="font-bold text-gray-900 text-lg">{getTranslatedName(item.name, lang)}</span>
                                        </td>
                                        <td className="px-8 py-6 text-center">
                                            <span className={`px-4 py-2 rounded-2xl text-sm font-black ${item.stock <= 5 ? 'bg-orange-100 text-orange-600' : 'bg-blue-50 text-blue-600'}`}>
                                                {item.stock ?? 0} {getText('units')}
                                            </span>
                                        </td>
                                        <td className="px-8 py-6 text-center text-xs font-bold text-gray-400 uppercase">
                                            {formatDate(item.lastUpdated)}
                                        </td>
                                        <td className="px-8 py-6">
                                            <div className="flex items-center justify-center gap-3" dir="ltr">
                                                <button onClick={() => handleManualAdjustment(item, -1)} className="w-10 h-10 rounded-xl bg-gray-100 hover:bg-red-500 hover:text-white transition-all font-black flex items-center justify-center">-</button>
                                                <button onClick={() => handleManualAdjustment(item, 1)} className="w-10 h-10 rounded-xl bg-gray-100 hover:bg-blue-600 hover:text-white transition-all font-black flex items-center justify-center">+</button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            </main>
        </div>
    );
}

export default App;