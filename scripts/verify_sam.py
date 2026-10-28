"""SAM preparation status only. Never performs a network call."""
import os


def main():
    print('Key present' if os.environ.get('META_API_KEY', '').strip() else 'Key missing')
    print('No network call made. SAM visual_verification: not_run. Explicit server demo-photo opt-in required.')
    print('Plug point: direct api.meta.ai files upload and responses input_image file_id, not Muse CLI.')


if __name__ == '__main__':
    main()
