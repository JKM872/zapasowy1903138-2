import { useState, useEffect } from 'react';
import { Bell, BellOff, X, Check, Loader2 } from 'lucide-react';

/**
 * NotificationPrompt - komponent do zarządzania powiadomieniami push
 * 
 * Funkcje:
 * - Prośba o pozwolenie na powiadomienia
 * - Rejestracja Service Worker
 * - Subskrypcja push notifications
 */

function NotificationPrompt({ onClose }) {
    const [permissionState, setPermissionState] = useState('default');
    const [isLoading, setIsLoading] = useState(false);
    const [isSupported, setIsSupported] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        // Check if notifications are supported
        if (!('Notification' in window) || !('serviceWorker' in navigator)) {
            setIsSupported(false);
            return;
        }

        setPermissionState(Notification.permission);
    }, []);

    const requestPermission = async () => {
        setIsLoading(true);
        setError(null);

        try {
            // Request notification permission
            const permission = await Notification.requestPermission();
            setPermissionState(permission);

            if (permission === 'granted') {
                // Register service worker
                await registerServiceWorker();

                // Show test notification
                showTestNotification();
            }
        } catch (err) {
            setError('Failed to request permission');
            console.error('Notification error:', err);
        } finally {
            setIsLoading(false);
        }
    };

    const registerServiceWorker = async () => {
        try {
            const registration = await navigator.serviceWorker.register('/sw.js');
            console.log('Service Worker registered:', registration);

            // Wait for the service worker to be ready
            await navigator.serviceWorker.ready;
            console.log('Service Worker ready');

            // Subscribe to push notifications (if push manager available)
            if ('PushManager' in window) {
                await subscribeToPush(registration);
            }
        } catch (err) {
            console.error('Service Worker registration failed:', err);
        }
    };

    const subscribeToPush = async (registration) => {
        try {
            // For demo purposes, we'll just subscribe without a server key
            // In production, you would use your VAPID public key
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                // applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
            });

            console.log('Push subscription:', subscription);

            // Send subscription to server
            // await fetch('/api/push/subscribe', {
            //   method: 'POST',
            //   body: JSON.stringify(subscription),
            //   headers: { 'Content-Type': 'application/json' }
            // });
        } catch (err) {
            console.log('Push subscription failed (this is normal without VAPID keys):', err);
        }
    };

    const showTestNotification = () => {
        if (Notification.permission === 'granted') {
            new Notification('BigOne', {
                body: 'Notifications enabled! You will receive alerts about new predictions.',
                icon: '/icons/icon-192x192.png',
                badge: '/icons/icon-72x72.png',
                tag: 'bigone-welcome'
            });
        }
    };

    if (!isSupported) {
        return (
            <div className="notification-prompt not-supported">
                <div className="prompt-content">
                    <BellOff size={24} className="prompt-icon warning" />
                    <div className="prompt-text">
                        <h4>Notifications Not Supported</h4>
                        <p>Your browser doesn't support push notifications.</p>
                    </div>
                    <button className="prompt-close" onClick={onClose}>
                        <X size={18} />
                    </button>
                </div>
            </div>
        );
    }

    if (permissionState === 'granted') {
        return (
            <div className="notification-prompt granted">
                <div className="prompt-content">
                    <Check size={24} className="prompt-icon success" />
                    <div className="prompt-text">
                        <h4>Notifications Enabled</h4>
                        <p>You'll receive alerts about new predictions.</p>
                    </div>
                    <button className="prompt-close" onClick={onClose}>
                        <X size={18} />
                    </button>
                </div>
            </div>
        );
    }

    if (permissionState === 'denied') {
        return (
            <div className="notification-prompt denied">
                <div className="prompt-content">
                    <BellOff size={24} className="prompt-icon error" />
                    <div className="prompt-text">
                        <h4>Notifications Blocked</h4>
                        <p>Enable notifications in your browser settings.</p>
                    </div>
                    <button className="prompt-close" onClick={onClose}>
                        <X size={18} />
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="notification-prompt">
            <div className="prompt-content">
                <Bell size={24} className="prompt-icon" />
                <div className="prompt-text">
                    <h4>Enable Notifications</h4>
                    <p>Get alerts about new qualifying predictions.</p>
                </div>
                <div className="prompt-actions">
                    <button
                        className="prompt-btn primary"
                        onClick={requestPermission}
                        disabled={isLoading}
                    >
                        {isLoading ? (
                            <Loader2 size={16} className="spin" />
                        ) : (
                            'Enable'
                        )}
                    </button>
                    <button
                        className="prompt-btn secondary"
                        onClick={onClose}
                    >
                        Later
                    </button>
                </div>
            </div>
            {error && (
                <div className="prompt-error">
                    {error}
                </div>
            )}

            <style jsx>{`
        .notification-prompt {
          position: fixed;
          bottom: 24px;
          right: 24px;
          background: var(--bg-secondary, #161b22);
          border: 1px solid var(--border-color, #30363d);
          border-radius: 12px;
          padding: 16px;
          max-width: 360px;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
          z-index: 1000;
          animation: slideIn 0.3s ease;
        }

        @keyframes slideIn {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .prompt-content {
          display: flex;
          align-items: flex-start;
          gap: 12px;
        }

        .prompt-icon {
          flex-shrink: 0;
          color: var(--accent-blue, #58a6ff);
        }

        .prompt-icon.success {
          color: var(--accent-green, #2ea043);
        }

        .prompt-icon.warning,
        .prompt-icon.error {
          color: var(--accent-red, #f85149);
        }

        .prompt-text {
          flex: 1;
        }

        .prompt-text h4 {
          margin: 0 0 4px;
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary, #e6edf3);
        }

        .prompt-text p {
          margin: 0;
          font-size: 13px;
          color: var(--text-secondary, #8b949e);
        }

        .prompt-actions {
          display: flex;
          gap: 8px;
          margin-top: 12px;
        }

        .prompt-btn {
          padding: 8px 16px;
          border-radius: 6px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
          border: none;
        }

        .prompt-btn.primary {
          background: var(--accent-green, #2ea043);
          color: white;
        }

        .prompt-btn.primary:hover:not(:disabled) {
          background: #3fb950;
        }

        .prompt-btn.primary:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .prompt-btn.secondary {
          background: transparent;
          color: var(--text-secondary, #8b949e);
          border: 1px solid var(--border-color, #30363d);
        }

        .prompt-btn.secondary:hover {
          background: var(--bg-tertiary, #21262d);
          color: var(--text-primary, #e6edf3);
        }

        .prompt-close {
          background: transparent;
          border: none;
          color: var(--text-muted, #6e7681);
          cursor: pointer;
          padding: 4px;
          border-radius: 4px;
        }

        .prompt-close:hover {
          background: var(--bg-tertiary, #21262d);
          color: var(--text-primary, #e6edf3);
        }

        .prompt-error {
          margin-top: 8px;
          padding: 8px;
          background: rgba(248, 81, 73, 0.1);
          border-radius: 6px;
          font-size: 12px;
          color: var(--accent-red, #f85149);
        }

        .notification-prompt.granted,
        .notification-prompt.denied,
        .notification-prompt.not-supported {
          padding: 12px 16px;
        }

        .spin {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        @media (max-width: 480px) {
          .notification-prompt {
            bottom: 16px;
            right: 16px;
            left: 16px;
            max-width: none;
          }
        }
      `}</style>
        </div>
    );
}

export default NotificationPrompt;
