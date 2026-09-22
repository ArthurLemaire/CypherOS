import defaults from './defaults.json';
import { manifest } from '../manifest';

/**
 * Initial runtime state. Leave `serverUrl` empty to get the setup page on first launch, or
 * fill it in (e.g. "http://127.0.0.1:8787") to have the phone come up already connected.
 */
export const OPENMUSE_CONFIG = {
  ...defaults,
  appId: manifest.id,
};
